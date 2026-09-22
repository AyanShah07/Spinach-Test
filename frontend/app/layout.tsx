import type { Metadata } from "next";
import "./globals.css";
import { SmoothScroll } from "@/components/smooth-scroll";

export const metadata: Metadata = {
  title: "MarTech Intelligence",
  description: "Campaign decision engine — assessment demo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen">
        <SmoothScroll>
          <header className="sticky top-0 z-50 border-b border-border/80 bg-background/80 backdrop-blur-md">
            <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
              <div>
                <p className="text-lg font-semibold tracking-tight">MarTech Intelligence</p>
                <p className="text-xs text-muted-foreground">
                  Customer engagement & campaign decisions
                </p>
              </div>
              <a className="text-sm text-primary underline-offset-4 hover:underline" href="/api-docs" target="_blank" rel="noreferrer">API documentation ↗</a>
            </div>
          </header>
          <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
        </SmoothScroll>
      </body>
    </html>
  );
}
