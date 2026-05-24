"use client";

import { Database, CheckCircle2, XCircle, Clock } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { TableMetrics } from "@/lib/types";
import { formatNumber, formatDuration, getRelativeTime } from "@/lib/utils";

interface TableMetricsProps {
  tables: TableMetrics[];
}

const statusConfig = {
  success: {
    icon: CheckCircle2,
    color: "text-emerald-600",
    badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  },
  failed: {
    icon: XCircle,
    color: "text-red-600",
    badge: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  },
  pending: {
    icon: Clock,
    color: "text-amber-600",
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  },
};

export function TableMetrics({ tables }: TableMetricsProps) {
  const totalRecords = tables.reduce((acc, t) => acc + t.recordsLoaded, 0);
  const totalTime = tables.reduce((acc, t) => acc + t.executionTime, 0);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              Métricas por Tabla SAP
            </CardTitle>
            <CardDescription>
              Registros procesados en la última ejecución
            </CardDescription>
          </div>
          <div className="text-right">
            <p className="text-2xl font-bold">{formatNumber(totalRecords)}</p>
            <p className="text-xs text-muted-foreground">
              Total en {formatDuration(totalTime)}
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[280px]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tabla</TableHead>
                <TableHead className="text-right">Extraídos</TableHead>
                <TableHead className="text-right">Cargados</TableHead>
                <TableHead className="text-right">Tiempo</TableHead>
                <TableHead className="text-right">Actualizado</TableHead>
                <TableHead>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tables.map((table) => {
                const config = statusConfig[table.status];
                const Icon = config.icon;
                const loadRate =
                  table.recordsExtracted > 0
                    ? (
                        (table.recordsLoaded / table.recordsExtracted) *
                        100
                      ).toFixed(1)
                    : "0";

                return (
                  <TableRow key={table.tableName}>
                    <TableCell className="font-mono font-medium">
                      {table.tableName}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {formatNumber(table.recordsExtracted)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {formatNumber(table.recordsLoaded)}
                      {loadRate !== "100.0" && (
                        <span className="text-xs text-muted-foreground ml-1">
                          ({loadRate}%)
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {formatDuration(table.executionTime)}
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {getRelativeTime(table.lastUpdated)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className={config.badge}>
                        <Icon className={`h-3 w-3 ${config.color}`} />
                      </Badge>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
