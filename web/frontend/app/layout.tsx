import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "投放作战室",
  description: "digital_marketing_agent 的对话式营销控制台",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
