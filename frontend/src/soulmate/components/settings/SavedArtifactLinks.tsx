import Link from "next/link";
import { SOULMATE_ROUTES } from "@/soulmate/domain";

export function SavedArtifactLinks({ sketch, report }: { sketch: boolean; report: boolean }) {
  if (!sketch && !report) return null;
  return (
    <nav aria-label="Saved artifacts" className="flex flex-wrap gap-2 pt-2">
      {sketch && (
        <Link href={SOULMATE_ROUTES.SKETCH} data-testid="saved-sketch-link" className="rounded-lg bg-white px-3 py-2 font-semibold text-purple-800">
          Open saved Sketch
        </Link>
      )}
      {report && (
        <Link href={SOULMATE_ROUTES.REPORT} data-testid="saved-report-link" className="rounded-lg bg-white px-3 py-2 font-semibold text-purple-800">
          Open saved Report
        </Link>
      )}
    </nav>
  );
}
