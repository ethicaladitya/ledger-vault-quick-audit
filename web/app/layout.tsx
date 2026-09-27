import "./style.css";
export const metadata = { title: "LedgerVault", description: "Evidence-first ITR working papers", robots: { index: false, follow: false } };
export const viewport = { width: "device-width", initialScale: 1 };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
