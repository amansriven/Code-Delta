import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("host") ?? "localhost:3000";
  const protocol = host.startsWith("localhost") || host.startsWith("127.0.0.1") ? "http" : "https";
  const origin = `${protocol}://${host}`;

  return {
    metadataBase: new URL(origin),
    title: {
      default: "CodeΔ — Evidence, not speculation",
      template: "%s · CodeΔ",
    },
    description:
      "Reproduce API behavior changes across pull requests and review the exact request and response evidence.",
    applicationName: "Code Delta",
    keywords: [
      "API regression testing",
      "GitHub pull requests",
      "FastAPI",
      "behavioral testing",
    ],
    openGraph: {
      type: "website",
      title: "CodeΔ — Your API changed. Know exactly how.",
      description:
        "Concrete API behavior from real requests across your base branch and pull request.",
      images: [
        {
          url: `${origin}/og.png`,
          width: 1731,
          height: 909,
          alt: "Code Delta — Your API changed. Know exactly how.",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: "CodeΔ — Evidence, not speculation",
      description:
        "Concrete API behavior from real requests across your base branch and pull request.",
      images: [`${origin}/og.png`],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <div id="main-content">{children}</div>
      </body>
    </html>
  );
}
