"use client";

import { useState, useEffect } from "react";
import {
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import type { ETLState } from "@/lib/types";
import { formatDuration, formatTime, getRelativeTime } from "@/lib/utils";

interface StatusPanelProps {
  state: ETLState;
  onTriggerETL: () => void;
}

const statusConfig = {
  idle: {
    icon: Clock,
    color: "text-muted-foreground",
    bg: "bg-muted",
    label: "Inactivo",
  },
  running: {
    icon: Loader2,
    color: "text-blue-600",
    bg: "bg-blue-50 dark:bg-blue-950",
    label: "En ejecución",
  },
  success: {
    icon: CheckCircle2,
    color: "text-emerald-600",
    bg: "bg-emerald-50 dark:bg-emerald-950",
    label: "Completado",
  },
  failed: {
    icon: XCircle,
    color: "text-red-600",
    bg: "bg-red-50 dark:bg-red-950",
    label: "Fallido",
  },
  warning: {
    icon: AlertTriangle,
    color: "text-amber-600",
    bg: "bg-amber-50 dark:bg-amber-950",
    label: "Advertencia",
  },
};

export function StatusPanel({ state, onTriggerETL }: StatusPanelProps) {
  const [elapsedTime, setElapsedTime] = useState(0);
  const config = statusConfig[state.status];
  const Icon = config.icon;

  useEffect(() => {
    if (state.status === "running" && state.startTime) {
      const interval = setInterval(() => {
        const elapsed = Math.floor(
          (Date.now() - new Date(state.startTime!).getTime()) / 1000
        );
        setElapsedTime(elapsed);
      }, 1000);
      return () => clearInterval(interval);
    }
    setElapsedTime(0);
  }, [state.status, state.startTime]);

  const isRunning = state.status === "running";
  const canTrigger = !state.isLocked && state.status !== "running";

  return (
    <Card className={config.bg}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg ${config.bg}`}>
              <Icon
                className={`h-6 w-6 ${config.color} ${isRunning ? "animate-spin" : ""}`}
              />
            </div>
            <div>
              <CardTitle className="text-lg">Estado del ETL</CardTitle>
              <CardDescription>
                {state.triggeredBy === "scheduled"
                  ? "Ejecución automática"
                  : state.triggeredBy === "manual"
                    ? "Ejecución manual"
                    : "Sin ejecución activa"}
              </CardDescription>
            </div>
          </div>
          <Badge
            variant={
              state.status === "running"
                ? "default"
                : state.status === "success"
                  ? "secondary"
                  : state.status === "failed"
                    ? "destructive"
                    : "outline"
            }
            className="text-sm px-3 py-1"
          >
            {config.label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isRunning && (
          <>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Progreso</span>
                <span className="font-medium">{state.progress}%</span>
              </div>
              <Progress value={state.progress} className="h-2" />
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Paso actual</span>
              <span className="font-medium">{state.currentStep}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Tiempo transcurrido</span>
              <span className="font-mono font-medium">
                {formatDuration(elapsedTime)}
              </span>
            </div>
            {state.startTime && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Iniciado</span>
                <span className="font-medium">{formatTime(state.startTime)}</span>
              </div>
            )}
          </>
        )}

        {!isRunning && state.endTime && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Última ejecución</span>
            <span className="font-medium">{getRelativeTime(state.endTime)}</span>
          </div>
        )}

        <div className="pt-2">
          <Button
            onClick={onTriggerETL}
            disabled={!canTrigger}
            className="w-full"
            variant={canTrigger ? "default" : "secondary"}
          >
            {isRunning ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ETL en ejecución...
              </>
            ) : state.isLocked ? (
              <>
                <AlertTriangle className="mr-2 h-4 w-4" />
                Sistema bloqueado
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                Ejecutar ETL Manual
              </>
            )}
          </Button>
          {state.isLocked && !isRunning && (
            <p className="text-xs text-muted-foreground text-center mt-2">
              Hay una ejecución automática en curso
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
