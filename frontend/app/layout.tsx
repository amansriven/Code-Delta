import type { Metadata } from "next";
import { headers } from "next/headers";
import "@fontsource-variable/manrope";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("host") ?? "localhost:3000";
  const protocol = host.startsWith("localhost") || host.startsWith("127.0.0.1") ? "http" : "https";
  const origin = `${protocol}://${host}`;

  return {
    metadataBase: new URL(origin),
    title: {
      default: "Delta Code — Ship API changes without the guesswork",
      template: "%s · Delta Code",
    },
    description:
      "Evidence-first API verification that shows exactly how pull requests change real behavior.",
    applicationName: "Delta Code",
    keywords: [
      "API regression testing",
      "GitHub pull requests",
      "FastAPI",
      "behavioral testing",
    ],
    openGraph: {
      type: "website",
      title: "Delta Code — Ship API changes without the guesswork.",
      description:
        "Run targeted requests against both branches and review only the behavior that actually changed.",
      images: [
        {
          url: `${origin}/og-v2.png`,
          width: 1731,
          height: 909,
          alt: "Delta Code — Ship API changes without the guesswork.",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: "Delta Code — Ship API changes without the guesswork.",
      description:
        "Evidence-first API verification for modern development teams.",
      images: [`${origin}/og-v2.png`],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <div id="main-content">{children}</div>
      </body>
    </html>
  );
}
