import type { NextConfig } from "next";

const BACKEND_URL =
  process.env.BACKEND_URL ||
  "https://analyseur-linkedin-influenceur-api.onrender.com";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
