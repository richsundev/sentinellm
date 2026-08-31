/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  eslint: {
    dirs: ["app", "components", "lib", "__tests__"],
  },
};

module.exports = nextConfig;
