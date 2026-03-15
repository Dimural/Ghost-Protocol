"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, ShieldAlert } from "lucide-react";

import { ReportView } from "@/components/ReportView";
import {
  getErrorMessage,
  getMatch,
  getReport,
  getReportExportUrl,
  type MatchReportResponse,
  type MatchStateResponse,
} from "@/lib/api";

type ReportPageProps = {
  params: {
    matchId: string;
  };
};

export default function ReportPage({ params }: ReportPageProps) {
  const matchId = params.matchId;
  const [match, setMatch] = useState<MatchStateResponse | null>(null);
  const [report, setReport] = useState<MatchReportResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;

    async function loadReportPage() {
      setIsLoading(true);
      setErrorMessage(null);

      try {
        const [nextMatch, nextReport] = await Promise.all([
          getMatch(matchId),
          getReport(matchId),
        ]);
        if (!isActive) {
          return;
        }

        setMatch(nextMatch);
        setReport(nextReport);
      } catch (error) {
        if (!isActive) {
          return;
        }

        setErrorMessage(getErrorMessage(error));
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    loadReportPage();

    return () => {
      isActive = false;
    };
  }, [matchId]);

  if (isLoading) {
    return (
      <main className="experience-shell">
        <section className="experience-section">
          <div className="experience-content">
            <div className="app-panel p-8 text-slate-200">
            Loading report for match {matchId}...
            </div>
          </div>
        </section>
      </main>
    );
  }

  if (errorMessage || !match || !report) {
    return (
      <main className="experience-shell">
        <section className="experience-section">
          <div className="experience-content max-w-4xl">
            <div className="app-panel p-8">
            <div className="flex items-center gap-3 text-rose-100">
              <ShieldAlert className="h-6 w-6" />
              <h1 className="text-2xl font-semibold">Report unavailable</h1>
            </div>
            <p className="mt-4 text-sm leading-6 text-rose-50/90">
              {errorMessage ||
                "This post-game report could not be loaded yet."}
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link
                href={`/match/${matchId}`}
                className="landing-button landing-button-secondary"
              >
                <ArrowLeft className="h-4 w-4" />
                Back to War Room
              </Link>
              <Link
                href="/"
                className="landing-button landing-button-secondary"
              >
                Return to setup
              </Link>
            </div>
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="experience-shell">
      <ReportView
        matchId={matchId}
        match={match}
        report={report}
        jsonExportUrl={getReportExportUrl(matchId, "json")}
        pdfExportUrl={getReportExportUrl(matchId, "pdf")}
      />
    </main>
  );
}
