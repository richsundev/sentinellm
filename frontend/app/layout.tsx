import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { FiltersProvider } from "@/lib/filters-context";

export const metadata: Metadata = {
  title: "SentinelLLM",
  description: "LLM reliability, evaluation & observability dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans antialiased">
        <FiltersProvider>
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <Topbar />
              <main className="flex-1 overflow-y-auto bg-base-950 p-6">
                {children}
              </main>
            </div>
          </div>
        </FiltersProvider>
      </body>
    </html>
  );
}
