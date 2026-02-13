import * as React from "react"
import { cn } from "@/lib/utils"
import { Radio, FileText } from "lucide-react"

export interface SourceBadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  source: 'LIVE' | 'PAPER' | 'live' | 'paper'
  showIcon?: boolean
  size?: 'sm' | 'md'
}

/**
 * Consistent badge for Live/Paper trading mode across the platform.
 * - Live: Red background with radio icon
 * - Paper: Orange/amber background with document icon
 */
function SourceBadge({ 
  source, 
  showIcon = true, 
  size = 'sm',
  className, 
  ...props 
}: SourceBadgeProps) {
  const isLive = source.toUpperCase() === 'LIVE'
  const isPaper = source.toUpperCase() === 'PAPER'
  
  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs gap-1",
    md: "px-2.5 py-1 text-sm gap-1.5"
  }
  
  const iconSize = size === 'sm' ? "h-3 w-3" : "h-3.5 w-3.5"

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md font-semibold transition-colors",
        sizeClasses[size],
        isLive && "bg-[var(--destructive)] text-white",
        isPaper && "bg-amber-500 text-black",
        className
      )}
      {...props}
    >
      {showIcon && isLive && <Radio className={iconSize} />}
      {showIcon && isPaper && <FileText className={iconSize} />}
      <span>{isLive ? 'Live' : 'Paper'}</span>
    </div>
  )
}

export { SourceBadge }
