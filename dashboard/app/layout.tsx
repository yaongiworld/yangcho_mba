import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "The Logic of Life-Care",
  description:
    "A daily-updating analysis of US lifestyle moments translated into K-Beauty marketing science.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
