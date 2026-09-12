import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VNStock Signals",
  description: "Tín hiệu chấm điểm cổ phiếu VN — pipeline v2f_v4",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
