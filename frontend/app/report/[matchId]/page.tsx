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
      <main className="px-6 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-7xl">
          <div className="rounded-[32px] border border-white/10 bg-[rgba(15,22,41,0.82)] p-8 text-slate-200 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
            Loading report for match {matchId}...
          </div>
        </div>
      </main>
    );
  }

  if (errorMessage || !match || !report) {
    return (
      <main className="px-6 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-4xl">
          <div className="rounded-[32px] border border-rose-300/20 bg-rose-400/10 p-8 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
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
                className="inline-flex items-center gap-2 rounded-full border border-rose-200/20 bg-white/10 px-5 py-2.5 text-sm font-medium text-rose-50 transition hover:bg-white/15"
              >
                <ArrowLeft className="h-4 w-4" />
                Back to War Room
              </Link>
              <Link
                href="/"
                className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-5 py-2.5 text-sm font-medium text-slate-100 transition hover:bg-white/10"
              >
                Return to setup
              </Link>
            </div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="px-6 py-8 sm:px-8 lg:px-12">
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
