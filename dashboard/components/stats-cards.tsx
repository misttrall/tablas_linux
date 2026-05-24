"use client";

import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  Database,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ETLStats } from "@/lib/types";
import { formatDuration, formatNumber, getRelativeTime } from "@/lib/utils";

interface StatsCardsProps {
  stats: ETLStats;
}

export function StatsCards({ stats }: StatsCardsProps) {
  const successRate =
    stats.totalExecutions > 0
      ? ((stats.successfulExecutions / stats.totalExecutions) * 100).toFixed(1)
      : "0";

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Total Ejecuciones
          </CardTitle>
          <Activity className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{stats.totalExecutions}</div>
          <p className="text-xs text-muted-foreground mt-1">
            {successRate}% tasa de éxito
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Exitosas
          </CardTitle>
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold text-emerald-600">
            {stats.successfulExecutions}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {stats.failedExecutions} fallidas
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Tiempo Promedio
          </CardTitle>
          <Clock className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">
            {formatDuration(stats.averageExecutionTime)}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            por ejecución
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            Registros Totales
          </CardTitle>
          <Database className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">
            {formatNumber(stats.totalRecordsProcessed)}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {stats.lastSuccessfulRun
              ? `Último: ${getRelativeTime(stats.lastSuccessfulRun)}`
              : "Sin ejecuciones"}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
