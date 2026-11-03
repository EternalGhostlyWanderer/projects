#include "test_asan.cpp"

TEST_CASE("Classic box") {
    CameraOptions camera_opts{.screen_width = 500,
                              .screen_height = 500,
                              .look_from = {-.5, 1.5, .98},
                              .look_to = {0., 1., 0.}};
    CheckImage("classic_box/CornellBox.obj", "classic_box/first.png", camera_opts, {4});
    camera_opts.look_from = {-.9, 1.9, -1};
    camera_opts.look_to = {0., 0., 0.};
    CheckImage("classic_box/CornellBox.obj", "classic_box/second.png", camera_opts, {4});
}

TEST_CASE("Mirrors") {
    CameraOptions camera_opts{.screen_width = 800,
                              .screen_height = 600,
                              .look_from = {2., 1.5, -.1},
                              .look_to = {1., 1.2, -2.8}};
    CheckImage("mirrors/scene.obj", "mirrors/result.png", camera_opts, {9});
}

TEST_CASE("Distorted box") {
    CameraOptions camera_opts{.screen_width = 500,
                              .screen_height = 500,
                              .look_from = {-0.5, 1.5, 1.98},
                              .look_to = {0., 1., 0.}};
    CheckImage("distorted_box/CornellBox.obj", "distorted_box/result.png", camera_opts, {4});
}

TEST_CASE("Deer") {
    CameraOptions camera_opts{.screen_width = 500,
                              .screen_height = 500,
                              .look_from = {100., 200., 150.},
                              .look_to = {0., 100., 0.}};
    CheckImage("deer/CERF_Free.obj", "deer/result.png", camera_opts, {1});
    RenderOptions render_opts{
        .depth = 4,
        .mode = RenderMode::kFull
    };

    // 3. Запускаем рендеринг (путь к .obj файлу укажи свой)
    std::string obj_path = "deer/CERF_Free.obj";

    Image image = Render(obj_path, camera_opts, render_opts);

    // 4. Сохраняем готовую картинку в формате PNG
    std::string output_path = "/home/anna/mydear.png";
    image.Write(output_path);
}
