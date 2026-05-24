"use client";

import { AlertCircle, Bug, Database, Link2, CheckCircle } from "lucide-react";
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
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import type { ETLError } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

interface ErrorsListProps {
  errors: ETLError[];
}

const errorTypeConfig = {
  extraction: { icon: Database, label: "Extracción" },
  transformation: { icon: Bug, label: "Transformación" },
  loading: { icon: Database, label: "Carga" },
  connection: { icon: Link2, label: "Conexión" },
  validation: { icon: CheckCircle, label: "Validación" },
};

const severityConfig = {
  low: {
    badge: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200",
    label: "Bajo",
  },
  medium: {
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    label: "Medio",
  },
  high: {
    badge: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
    label: "Alto",
  },
  critical: {
    badge: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
    label: "Crítico",
  },
};

export function ErrorsList({ errors }: ErrorsListProps) {
  const unresolvedCount = errors.filter((e) => !e.resolved).length;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5" />
              Errores Recientes
              {unresolvedCount > 0 && (
                <Badge variant="destructive" className="ml-2">
                  {unresolvedCount} sin resolver
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              Log de errores de las ejecuciones ETL
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[400px]">
          {errors.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <CheckCircle className="h-8 w-8 mb-2 opacity-50" />
              <p>No hay errores registrados</p>
            </div>
          ) : (
            <Accordion type="single" collapsible className="space-y-2">
              {errors.map((error) => {
                const typeConfig = errorTypeConfig[error.errorType];
                const sevConfig = severityConfig[error.severity];
                const TypeIcon = typeConfig.icon;

                return (
                  <AccordionItem
                    key={error.id}
                    value={error.id}
                    className={`border rounded-lg px-4 ${
                      !error.resolved
                        ? "border-red-200 dark:border-red-800"
                        : ""
                    }`}
                  >
                    <AccordionTrigger className="hover:no-underline">
                      <div className="flex items-center gap-3 text-left">
                        <TypeIcon className="h-4 w-4 text-muted-foreground" />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium truncate">
                              {error.message.slice(0, 50)}
                              {error.message.length > 50 && "..."}
                            </span>
                            <Badge variant="secondary" className={sevConfig.badge}>
                              {sevConfig.label}
                            </Badge>
                            {error.resolved && (
                              <Badge
                                variant="outline"
                                className="bg-emerald-50 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200"
                              >
                                Resuelto
                              </Badge>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
                            <span>{formatDateTime(error.timestamp)}</span>
                            <span>•</span>
                            <span>{typeConfig.label}</span>
                            {error.tableName && (
                              <>
                                <span>•</span>
                                <span className="font-mono">{error.tableName}</span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent>
                      <div className="space-y-3 pt-2">
                        <div>
                          <h4 className="text-sm font-medium mb-1">Mensaje</h4>
                          <p className="text-sm text-muted-foreground">
                            {error.message}
                          </p>
                        </div>
                        {error.stackTrace && (
                          <div>
                            <h4 className="text-sm font-medium mb-1">
                              Stack Trace
                            </h4>
                            <pre className="text-xs bg-muted p-3 rounded-lg overflow-x-auto font-mono">
                              {error.stackTrace}
                            </pre>
                          </div>
                        )}
                        <div className="flex items-center gap-4 text-xs text-muted-foreground">
                          <span>
                            Ejecución:{" "}
                            <span className="font-mono">{error.executionId}</span>
                          </span>
                        </div>
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                );
              })}
            </Accordion>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
