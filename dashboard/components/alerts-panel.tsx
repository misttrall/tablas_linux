"use client";

import { Bell, AlertCircle, AlertTriangle, Info, X } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import type { Alert } from "@/lib/types";
import { getRelativeTime } from "@/lib/utils";

interface AlertsPanelProps {
  alerts: Alert[];
  onDismiss?: (id: string) => void;
  onMarkAsRead?: (id: string) => void;
}

const alertConfig = {
  error: {
    icon: AlertCircle,
    color: "text-red-600",
    bg: "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800",
  },
  warning: {
    icon: AlertTriangle,
    color: "text-amber-600",
    bg: "bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800",
  },
  info: {
    icon: Info,
    color: "text-blue-600",
    bg: "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800",
  },
};

export function AlertsPanel({ alerts, onDismiss, onMarkAsRead }: AlertsPanelProps) {
  const unreadCount = alerts.filter((a) => !a.read).length;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" />
              Alertas
              {unreadCount > 0 && (
                <Badge variant="destructive" className="ml-2">
                  {unreadCount}
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              Notificaciones del sistema ETL
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[280px]">
          {alerts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
              <Bell className="h-8 w-8 mb-2 opacity-50" />
              <p>No hay alertas</p>
            </div>
          ) : (
            <div className="space-y-3">
              {alerts.map((alert) => {
                const config = alertConfig[alert.type];
                const Icon = config.icon;

                return (
                  <div
                    key={alert.id}
                    className={`p-3 rounded-lg border ${config.bg} ${
                      !alert.read ? "ring-2 ring-offset-2 ring-offset-background" : ""
                    }`}
                    onClick={() => !alert.read && onMarkAsRead?.(alert.id)}
                  >
                    <div className="flex items-start gap-3">
                      <Icon className={`h-5 w-5 mt-0.5 ${config.color}`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <h4 className="font-medium text-sm truncate">
                            {alert.title}
                          </h4>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 shrink-0"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDismiss?.(alert.id);
                            }}
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">
                          {alert.message}
                        </p>
                        <p className="text-xs text-muted-foreground mt-2">
                          {getRelativeTime(alert.timestamp)}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
