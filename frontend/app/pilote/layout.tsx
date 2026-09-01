import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Cibl — Mode Pilote gratuit",
  description:
    "1 post par jour, jusqu'à 3 contacts, et un groupe privé de missions et de stratégies d'acquisition. Gratuit, sans carte.",
};

export default function PiloteLayout({ children }: { children: React.ReactNode }) {
  return children;
}
