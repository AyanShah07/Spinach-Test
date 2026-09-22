/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  turbopack: { root: __dirname },
  outputFileTracingRoot: __dirname,
  // Allow calling the backend from the browser during demo
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      { source: "/api-docs", destination: `${backend}/docs` },
      { source: "/openapi.json", destination: `${backend}/openapi.json` },
      {
        source: "/api/backend/:path*",
        destination: `${backend}/api/v1/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
