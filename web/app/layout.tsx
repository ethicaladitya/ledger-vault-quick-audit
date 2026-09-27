import "./style.css";
export const metadata = { title: "LedgerVault · ITR working papers for India", description: "Turn a year of bank and credit-card statements into a CA-ready working paper: categorised, reconciled and traceable. Self-hosted and private.", robots: { index: false, follow: false } };
export const viewport = { width: "device-width", initialScale: 1 };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
