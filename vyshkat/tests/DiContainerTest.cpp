#include <gtest/gtest.h>

#include <memory>
#include <stdexcept>
#include <string>

#include "di/DiContainer.h"

namespace {

class Greeter {
public:
    virtual ~Greeter() = default;
    virtual std::string name() const = 0;
};

class RealGreeter : public Greeter {
public:
    std::string name() const override { return "real"; }
};

class FakeGreeter : public Greeter {
public:
    std::string name() const override { return "fake"; }
};

class Consumer {
public:
    explicit Consumer(std::shared_ptr<Greeter> greeter)
        : greeter_(std::move(greeter)) {}

    std::string greeterName() const { return greeter_->name(); }

private:
    std::shared_ptr<Greeter> greeter_;
};

struct NodeA {};
struct NodeB {};

}  // namespace

class DiContainerTest : public ::testing::Test {
protected:
    DiContainer container;
};

TEST_F(DiContainerTest, ResolvesRegisteredType) {
    container.registerType<Greeter>([](DiContainer&) {
        return std::make_shared<RealGreeter>();
    });

    EXPECT_EQ(container.resolve<Greeter>()->name(), "real");
}

TEST_F(DiContainerTest, ReturnsSameInstanceEveryTime) {
    container.registerType<Greeter>([](DiContainer&) {
        return std::make_shared<RealGreeter>();
    });

    const auto first = container.resolve<Greeter>();
    const auto second = container.resolve<Greeter>();

    EXPECT_TRUE(first.get() == second.get());
}

TEST_F(DiContainerTest, CreatesServiceLazilyAndOnlyOnce) {
    int created = 0;
    container.registerType<Greeter>([&created](DiContainer&) {
        ++created;
        return std::make_shared<RealGreeter>();
    });

    EXPECT_EQ(created, 0);

    container.resolve<Greeter>();
    container.resolve<Greeter>();

    EXPECT_EQ(created, 1);
}

TEST_F(DiContainerTest, UnregisteredTypeIsRefused) {
    EXPECT_THROW(container.resolve<Greeter>(), std::logic_error);
}

TEST_F(DiContainerTest, ResolvesRegisteredInstance) {
    const auto instance = std::make_shared<FakeGreeter>();
    container.registerInstance<Greeter>(instance);

    EXPECT_TRUE(container.resolve<Greeter>().get() == instance.get());
}

TEST_F(DiContainerTest, LaterRegistrationReplacesEarlierOne) {
    container.registerType<Greeter>([](DiContainer&) {
        return std::make_shared<RealGreeter>();
    });
    container.registerInstance<Greeter>(std::make_shared<FakeGreeter>());

    EXPECT_EQ(container.resolve<Greeter>()->name(), "fake");
}

TEST_F(DiContainerTest, DependencyIsTakenFromContainer) {
    container.registerType<Greeter>([](DiContainer&) {
        return std::make_shared<RealGreeter>();
    });
    container.registerType<Consumer>([](DiContainer& c) {
        return std::make_shared<Consumer>(c.resolve<Greeter>());
    });

    EXPECT_EQ(container.resolve<Consumer>()->greeterName(), "real");
}

TEST_F(DiContainerTest, ReplacedDependencyReachesConsumer) {
    container.registerType<Greeter>([](DiContainer&) {
        return std::make_shared<RealGreeter>();
    });
    container.registerType<Consumer>([](DiContainer& c) {
        return std::make_shared<Consumer>(c.resolve<Greeter>());
    });

    container.registerInstance<Greeter>(std::make_shared<FakeGreeter>());

    EXPECT_EQ(container.resolve<Consumer>()->greeterName(), "fake");
}

TEST_F(DiContainerTest, CircularDependencyIsDetected) {
    container.registerType<NodeA>([](DiContainer& c) {
        c.resolve<NodeB>();
        return std::make_shared<NodeA>();
    });
    container.registerType<NodeB>([](DiContainer& c) {
        c.resolve<NodeA>();
        return std::make_shared<NodeB>();
    });

    EXPECT_THROW(container.resolve<NodeA>(), std::logic_error);
}

TEST_F(DiContainerTest, FailedCreationCanBeRetried) {
    int attempts = 0;
    container.registerType<Greeter>([&attempts](DiContainer&) {
        ++attempts;

        if (attempts == 1) {
            throw std::runtime_error("first attempt fails");
        }

        return std::make_shared<RealGreeter>();
    });

    EXPECT_THROW(container.resolve<Greeter>(), std::runtime_error);
    EXPECT_EQ(container.resolve<Greeter>()->name(), "real");
}

TEST_F(DiContainerTest, CreatorReturningNullIsRefused) {
    container.registerType<Greeter>([](DiContainer&) {
        return std::shared_ptr<Greeter>();
    });

    EXPECT_THROW(container.resolve<Greeter>(), std::logic_error);
}

TEST_F(DiContainerTest, EmptyCreatorAndNullInstanceAreRefused) {
    EXPECT_THROW(
        container.registerType<Greeter>(DiContainer::Creator<Greeter>()),
        std::invalid_argument);
    EXPECT_THROW(
        container.registerInstance<Greeter>(std::shared_ptr<Greeter>()),
        std::invalid_argument);
}