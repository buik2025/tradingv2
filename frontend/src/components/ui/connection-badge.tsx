import * as React from "react"
import { cn } from "@/lib/utils"
import { Wifi, WifiOff } from "lucide-react"

export interface ConnectionBadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  connected: boolean
  size?: 'sm' | 'md'
}

/**
 * Consistent badge for WebSocket connection status across the platform.
 * - Connected: Green with Wifi icon showing "Live"
 * - Disconnected: Gray with WifiOff icon showing "Offline"
 */
function ConnectionBadge({ 
  connected, 
  size = 'sm',
  className, 
  ...props 
}: ConnectionBadgeProps) {
  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs gap-1",
    md: "px-2.5 py-1 text-sm gap-1.5"
  }
  
  const iconSize = size === 'sm' ? "h-3 w-3" : "h-3.5 w-3.5"

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md font-semibold border transition-colors",
        sizeClasses[size],
        connected 
          ? "text-[var(--profit)] border-[var(--profit)] bg-[var(--profit)]/10" 
          : "text-[var(--muted-foreground)] border-[var(--border)] bg-[var(--muted)]",
        className
      )}
      {...props}
    >
      {connected ? (
        <>
          <Wifi className={iconSize} />
          <span>Live</span>
        </>
      ) : (
        <>
          <WifiOff className={iconSize} />
          <span>Offline</span>
        </>
      )}
    </div>
  )
}

export { ConnectionBadge }
