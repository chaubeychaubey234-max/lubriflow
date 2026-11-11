import type { Metadata } from "next";
import "./styles.css";
export const metadata: Metadata = {
  title: "LubriFlow · Purchasing workspace",
  description: "Industrial purchasing, inventory and financial controls.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
