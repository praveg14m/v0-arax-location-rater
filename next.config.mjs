/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  images: {
    unoptimized: true,
  },
  // Forward /api/* requests to the Python serverless functions in api/ at the repo root.
  // On Vercel this routing happens automatically; this rewrite makes local `next dev`
  // and downstream `vercel dev` flows behave consistently.
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: "/api/:path*",
          destination: "/api/:path*",
        },
      ],
    }
  },
}

export default nextConfig
