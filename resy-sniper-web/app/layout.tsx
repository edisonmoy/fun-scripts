import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Resy sniper targets",
  description: "Manage reservations the Resy sniper bot is watching",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
