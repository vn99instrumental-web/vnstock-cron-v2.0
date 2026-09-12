/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Ảnh không dùng ở E2; bật khi cần. Không expose secret nào ở đây.
  experimental: {
    // typedRoutes: true, // bật khi routes ổn định
  },
};

export default nextConfig;
