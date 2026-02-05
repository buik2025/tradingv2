import { useAuthStore } from '@/stores/authStore';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { User, Shield, Bell } from 'lucide-react';

export function Settings() {
  const { user } = useAuthStore();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-[var(--muted-foreground)]">Manage your account and preferences</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <User className="h-5 w-5 text-[var(--muted-foreground)]" />
              <CardTitle>Profile</CardTitle>
            </div>
            <CardDescription>Your account information</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {user ? (
              <>
                <div className="flex justify-between">
                  <span className="text-[var(--muted-foreground)]">User ID</span>
                  <span className="font-medium">{user.user_id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--muted-foreground)]">Name</span>
                  <span className="font-medium">{user.user_name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--muted-foreground)]">Email</span>
                  <span className="font-medium">{user.email}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--muted-foreground)]">Broker</span>
                  <Badge variant="outline">{user.broker}</Badge>
                </div>
              </>
            ) : (
              <p className="text-[var(--muted-foreground)]">Not logged in</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-[var(--muted-foreground)]" />
              <CardTitle>Risk Management</CardTitle>
            </div>
            <CardDescription>Trading risk parameters</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-between">
              <span className="text-[var(--muted-foreground)]">Max Margin</span>
              <span className="font-medium">40%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--muted-foreground)]">Max Loss/Trade</span>
              <span className="font-medium">1%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--muted-foreground)]">Max Daily Loss</span>
              <span className="font-medium">3%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--muted-foreground)]">Max Positions</span>
              <span className="font-medium">3</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Bell className="h-5 w-5 text-[var(--muted-foreground)]" />
              <CardTitle>Notifications</CardTitle>
            </div>
            <CardDescription>Alert preferences</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-[var(--muted-foreground)] text-sm">
              Notification settings coming soon...
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
