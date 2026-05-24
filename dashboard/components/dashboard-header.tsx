"use client";

import { useState } from "react";
import {
  Database,
  RefreshCw,
  Bell,
  Settings,
  Play,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ETLStatus } from "@/lib/types";

interface DashboardHeaderProps {
  status: ETLStatus;
  alertCount: number;
  onTriggerETL: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
}

export function DashboardHeader({
  status,
  alertCount,
  onTriggerETL,
  onRefresh,
  isRefreshing,
}: DashboardHeaderProps) {
  const [isTriggering, setIsTriggering] = useState(false);

  const isRunning = status === "running";
  const canTrigger = status === "idle" || status === "error";

  const handleTrigger = async () => {
    if (!canTrigger) return;
    setIsTriggering(true);
    onTriggerETL();
    setTimeout(() => setIsTriggering(false), 2000);
  };

  return (
    <header className="border-b border-border bg-card">
      <div className="container mx-auto px-4 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary">
              <Database className="h-5 w-5 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-foreground">
                ETL Dashboard
              </h1>
              <p className="text-sm text-muted-foreground">
                SAP to SQL Server Pipeline
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={onRefresh}
                    disabled={isRefreshing}
                  >
                    <RefreshCw
                      className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`}
                    />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Actualizar datos</TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="outline" size="icon" className="relative">
                    <Bell className="h-4 w-4" />
                    {alertCount > 0 && (
                      <Badge
                        variant="destructive"
                        className="absolute -right-1 -top-1 h-5 w-5 rounded-full p-0 text-xs flex items-center justify-center"
                      >
                        {alertCount > 9 ? "9+" : alertCount}
                      </Badge>
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {alertCount > 0
                    ? `${alertCount} alertas activas`
                    : "Sin alertas"}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="outline" size="icon">
                    <Settings className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Configuración</TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    onClick={handleTrigger}
                    disabled={!canTrigger || isTriggering}
                    className={
                      isRunning
                        ? "bg-amber-600 hover:bg-amber-600 cursor-not-allowed"
                        : ""
                    }
                  >
                    {isRunning ? (
                      <>
                        <AlertCircle className="mr-2 h-4 w-4" />
                        ETL en Ejecución
                      </>
                    ) : isTriggering ? (
                      <>
                        <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                        Iniciando...
                      </>
                    ) : (
                      <>
                        <Play className="mr-2 h-4 w-4" />
                        Ejecutar ETL
                      </>
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {isRunning
                    ? "El ETL está en ejecución. Espera a que termine."
                    : "Iniciar ejecución manual del ETL"}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      </div>
    </header>
  );
}
