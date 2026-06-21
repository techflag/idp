export type AuthUserRole = 'admin' | 'user' | 'customer'

export interface AuthUser {
  id: string
  username: string
  role: AuthUserRole
  displayName: string
  customerIds: string[]
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  user: AuthUser
}
