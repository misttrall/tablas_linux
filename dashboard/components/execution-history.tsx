"use client";

import { CheckCircle2, XCircle, Clock, User, Timer } from "lucide-react";
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
import type { ETLExecution } from "@/lib/types";
import { formatDateTime, formatDuration, formatNumber } from "@/lib/utils";

interface ExecutionHistoryProps {
  executions: ETLExecution[];
}

const statusConfig = {
  success: {
    icon: CheckCircle2,
    color: "text-emerald-600",
    badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
    label: "Exitoso",
  },
  failed: {
    icon: XCircle,
    color: "text-red-600",
    badge: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    label: "Fallido",
  },
  running: {
    icon: Clock,
    color: "text-blue-600",
    badge: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    label: "Ejecutando",
  },
  idle: {
    icon: Clock,
    color: "text-muted-foreground",
    badge: "bg-muted text-muted-foreground",
    label: "Inactivo",
  },
  warning: {
    icon: Clock,
    color: "text-amber-600",
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    label: "Advertencia",
  },
};

export function ExecutionHistory({ executions }: ExecutionHistoryProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Timer className="h-5 w-5" />
          Historial de Ejecuciones
        </CardTitle>
        <CardDescription>
          Últimas {executions.length} ejecuciones del proceso ETL
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[300px]">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Inicio</TableHead>
                <TableHead>Duración</TableHead>
                <TableHead>Registros</TableHead>
                <TableHead>Tablas</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {executions.map((execution) => {
                const config = statusConfig[execution.status];
                const Icon = config.icon;

                return (
                  <TableRow key={execution.id}>
                    <TableCell className="font-mono text-xs">
                      {execution.id.split("-").pop()}
                    </TableCell>
                    <TableCell className="text-sm">
                      {formatDateTime(execution.startTime)}
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {execution.duration
                        ? formatDuration(execution.duration)
                        : "-"}
                    </TableCell>
                    <TableCell className="text-sm">
                      {formatNumber(execution.totalRecords)}
                    </TableCell>
                    <TableCell className="text-sm">
                      {execution.tablesProcessed}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {execution.triggeredBy === "manual" ? (
                          <User className="h-3 w-3" />
                        ) : (
                          <Clock className="h-3 w-3" />
                        )}
                        <span className="text-xs capitalize">
                          {execution.triggeredBy === "manual"
                            ? "Manual"
                            : "Auto"}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className={config.badge}>
                        <Icon className={`h-3 w-3 mr-1 ${config.color}`} />
                        {config.label}
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
