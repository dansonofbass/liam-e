// i18n-exempt: route path.
import { createFileRoute, Outlet, useLocation } from '@tanstack/react-router'
import { TasksPage } from '../../tasks/TasksPage'
import { taskSearchSchema } from '../../tasks/filters'
export const Route = createFileRoute('/_app/tasks')({ validateSearch: taskSearchSchema, component: TasksRoute })
function TasksRoute() {
  const path = useLocation({ select: location => location.pathname })
  return path === '/tasks' ? <TasksPage /> : <Outlet />
}
