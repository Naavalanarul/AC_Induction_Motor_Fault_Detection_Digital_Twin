import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { LoginForm } from './LoginForm'

const mockLogin = vi.fn()

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    login: mockLogin,
    session: null,
    logout: vi.fn(),
    can: () => true,
  }),
}))

describe('LoginForm - Eye icon and Mode Selector', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockLogin.mockResolvedValue(undefined)
  })

  it('renders password masked by default with accessible eye button', () => {
    render(<LoginForm />)
    const passwordInput = screen.getByLabelText('Password')
    expect(passwordInput).toHaveAttribute('type', 'password')

    const eyeBtn = screen.getByRole('button', { name: 'Show password (hold)' })
    expect(eyeBtn).toBeInTheDocument()
    expect(eyeBtn).toHaveAttribute('type', 'button')
    expect(eyeBtn).toHaveAttribute('aria-pressed', 'false')
  })

  it('reveals password on pointerdown and masks again on pointerup', () => {
    render(<LoginForm />)
    const passwordInput = screen.getByLabelText('Password')
    const eyeBtn = screen.getByRole('button', { name: 'Show password (hold)' })

    fireEvent.pointerDown(eyeBtn)
    expect(passwordInput).toHaveAttribute('type', 'text')
    expect(eyeBtn).toHaveAttribute('aria-pressed', 'true')

    fireEvent.pointerUp(eyeBtn)
    expect(passwordInput).toHaveAttribute('type', 'password')
    expect(eyeBtn).toHaveAttribute('aria-pressed', 'false')
  })

  it('masks password on pointerleave and blur', () => {
    render(<LoginForm />)
    const passwordInput = screen.getByLabelText('Password')
    const eyeBtn = screen.getByRole('button', { name: 'Show password (hold)' })

    fireEvent.pointerDown(eyeBtn)
    expect(passwordInput).toHaveAttribute('type', 'text')

    fireEvent.pointerLeave(eyeBtn)
    expect(passwordInput).toHaveAttribute('type', 'password')

    fireEvent.pointerDown(eyeBtn)
    expect(passwordInput).toHaveAttribute('type', 'text')

    fireEvent.blur(passwordInput)
    expect(passwordInput).toHaveAttribute('type', 'password')
  })

  it('supports keyboard press-and-hold with Space and Enter on eye button', () => {
    render(<LoginForm />)
    const passwordInput = screen.getByLabelText('Password')
    const eyeBtn = screen.getByRole('button', { name: 'Show password (hold)' })

    // Space key
    fireEvent.keyDown(eyeBtn, { key: ' ' })
    expect(passwordInput).toHaveAttribute('type', 'text')
    fireEvent.keyUp(eyeBtn, { key: ' ' })
    expect(passwordInput).toHaveAttribute('type', 'password')

    // Enter key
    fireEvent.keyDown(eyeBtn, { key: 'Enter' })
    expect(passwordInput).toHaveAttribute('type', 'text')
    fireEvent.keyUp(eyeBtn, { key: 'Enter' })
    expect(passwordInput).toHaveAttribute('type', 'password')
  })

  it('does not submit the form when clicking the eye button', async () => {
    render(<LoginForm />)
    const usernameInput = screen.getByLabelText('Username')
    const passwordInput = screen.getByLabelText('Password')
    const eyeBtn = screen.getByRole('button', { name: 'Show password (hold)' })

    await userEvent.type(usernameInput, 'operator')
    await userEvent.type(passwordInput, 'secret123')

    fireEvent.pointerDown(eyeBtn)
    fireEvent.pointerUp(eyeBtn)

    expect(mockLogin).not.toHaveBeenCalled()
  })

  it('allows selecting target mode and passes selected mode to onLoginSuccess', async () => {
    const handleSuccess = vi.fn()
    render(<LoginForm onLoginSuccess={handleSuccess} />)

    const liveBtn = screen.getByRole('radio', { name: 'Live twin' })
    const staticBtn = screen.getByRole('radio', { name: 'Static analysis' })

    expect(liveBtn).toHaveAttribute('aria-checked', 'true')
    expect(staticBtn).toHaveAttribute('aria-checked', 'false')

    // Switch to static
    await userEvent.click(staticBtn)
    expect(liveBtn).toHaveAttribute('aria-checked', 'false')
    expect(staticBtn).toHaveAttribute('aria-checked', 'true')

    const usernameInput = screen.getByLabelText('Username')
    const passwordInput = screen.getByLabelText('Password')
    const submitBtn = screen.getByRole('button', { name: 'Sign in' })

    await userEvent.type(usernameInput, 'operator')
    await userEvent.type(passwordInput, 'secret123')
    await userEvent.click(submitBtn)

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('operator', 'secret123')
      expect(handleSuccess).toHaveBeenCalledWith('static')
    })
  })

  it('defaults to live mode and passes live on successful sign in', async () => {
    const handleSuccess = vi.fn()
    render(<LoginForm onLoginSuccess={handleSuccess} />)

    const usernameInput = screen.getByLabelText('Username')
    const passwordInput = screen.getByLabelText('Password')
    const submitBtn = screen.getByRole('button', { name: 'Sign in' })

    await userEvent.type(usernameInput, 'operator')
    await userEvent.type(passwordInput, 'secret123')
    await userEvent.click(submitBtn)

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('operator', 'secret123')
      expect(handleSuccess).toHaveBeenCalledWith('live')
    })
  })
})
