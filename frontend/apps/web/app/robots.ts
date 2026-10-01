import { MetadataRoute } from "next";
import { config } from "@/lib/config";

export default function robots(): MetadataRoute.Robots {
  const baseUrl = config.siteUrl;

  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/api/", "/settings/", "/portfolio/", "/wallet/", "/orders/", "/positions/"],
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
    host: baseUrl,
  };
}
