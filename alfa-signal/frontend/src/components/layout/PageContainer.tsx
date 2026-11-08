import type { ReactNode } from "react";

type PageContainerProps = {
  children: ReactNode;
};

export function PageContainer({ children }: PageContainerProps) {
  return <div className="w-full px-4 py-5 sm:px-6 lg:px-6 lg:py-5">{children}</div>;
}
