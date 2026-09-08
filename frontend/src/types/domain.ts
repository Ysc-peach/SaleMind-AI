export type Role = 'admin' | 'sales' | 'presales'
export interface User { id: number; username: string; role: Role; email: string; first_name: string; last_name: string }
