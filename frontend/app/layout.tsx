import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Delphi — Customer Intelligence",
  description:
    "A multi-agent customer-intelligence layer that federates siloed feedback sources behind one chat interface.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
