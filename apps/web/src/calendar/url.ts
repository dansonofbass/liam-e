import { todayLocal } from './state'

export type CalendarView = 'month' | 'week' | 'day' | 'list'

export function parseSearch(search: Record<string, unknown>, isMobile: boolean): { view: CalendarView; date: string } {
  const views: CalendarView[] = ['month', 'week', 'day', 'list']
  const view = views.includes(search.view as CalendarView) ? search.view as CalendarView : isMobile ? 'day' : 'week'
  const candidate = search.date
  const date = typeof candidate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(candidate) && Number.isFinite(Date.parse(candidate)) && new Date(candidate).toISOString().slice(0, 10) === candidate ? candidate : todayLocal()
  return { view, date }
}
