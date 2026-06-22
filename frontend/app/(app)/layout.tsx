import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Cibl",
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
