import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/soulmate/:path*",
        destination: "http://127.0.0.1:8000/api/soulmate/:path*",
      },
    ];
  },
};

export default nextConfig;
