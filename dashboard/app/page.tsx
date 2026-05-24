"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DashboardHeader } from "@/components/dashboard-header";
import { StatusPanel } from "@/components/status-panel";
import { StatsCards } from "@/components/stats-cards";
import { ExecutionHistory } from "@/components/execution-history";
import { TableMetrics } from "@/components/table-metrics";
import { AlertsPanel } from "@/components/alerts-panel";
import { MetricsCharts } from "@/components/metrics-charts";
import { ErrorsList } from "@/components/errors-list";
import {
  mockETLState,
  mockExecutions,
  mockTableMetrics,
  mockAlerts,
  mockDailyMetrics,
  mockErrors,
  mockStats,
} from "@/lib/mock-data";

export default function Dashboard() {
  const [currentState, setCurrentState] = useState(mockETLState);
  const [isTriggering, setIsTriggering] = useState(false);

  const handleTriggerETL = async () => {
    if (currentState.status === "running" || isTriggering) {
      return;
    }

    setIsTriggering(true);

    // Simulate API call to trigger ETL
    await new Promise((resolve) => setTimeout(resolve, 1500));

    // Update state to running (in real implementation, this comes from API)
    setCurrentState({
      ...currentState,
      status: "running",
      currentStep: "Extrayendo datos de SAP...",
      progress: 0,
      startTime: new Date().toISOString(),
      triggeredBy: "manual",
      isLocked: true,
    });

    setIsTriggering(false);
  };

  const activeAlerts = mockAlerts.filter((a) => !a.read);

  return (
    <div className="min-h-screen flex flex-col">
      <DashboardHeader alertCount={activeAlerts.length} />

      <main className="flex-1 container mx-auto px-4 py-6 max-w-7xl">
        <div className="flex flex-col gap-6">
          {/* Status Panel - Hero section */}
          <StatusPanel
            state={currentState}
            onTriggerETL={handleTriggerETL}
          />

          {/* Stats Overview */}
          <StatsCards stats={mockStats} />

          {/* Alerts Section - Show when there are active alerts */}
          {activeAlerts.length > 0 && <AlertsPanel alerts={activeAlerts} />}

          {/* Main Content Tabs */}
          <Tabs defaultValue="overview" className="w-full">
            <TabsList className="grid w-full grid-cols-4 lg:w-auto lg:inline-grid">
              <TabsTrigger value="overview">Resumen</TabsTrigger>
              <TabsTrigger value="tables">Tablas</TabsTrigger>
              <TabsTrigger value="history">Historial</TabsTrigger>
              <TabsTrigger value="errors">Errores</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-6">
              <MetricsCharts dailyMetrics={mockDailyMetrics} />
            </TabsContent>

            <TabsContent value="tables" className="mt-6">
              <TableMetrics tables={mockTableMetrics} />
            </TabsContent>

            <TabsContent value="history" className="mt-6">
              <ExecutionHistory executions={mockExecutions} />
            </TabsContent>

            <TabsContent value="errors" className="mt-6">
              <ErrorsList errors={mockErrors} />
            </TabsContent>
          </Tabs>
        </div>
      </main>
    </div>
  );
}
