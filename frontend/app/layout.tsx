import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Analytics from "./components/Analytics";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Cibl — Stratégie de contenu LinkedIn",
  description: "Décrypte la stratégie de contenu LinkedIn avec des stats déterministes et une synthèse IA.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fr">
      <body className={`${inter.variable} ${jetbrains.variable}`}>
        {children}
        <Analytics />
      </body>
    </html>
  );
}
