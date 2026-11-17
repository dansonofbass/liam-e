// i18n-exempt: route path.
import { createFileRoute } from '@tanstack/react-router'
import { TaskDetail } from '../../../tasks/TaskDetail'
export const Route = createFileRoute('/_app/tasks/$taskId')({ component: TaskRoute })
function TaskRoute() {
  const { taskId } = Route.useParams()
  return <TaskDetail key={taskId} id={taskId} />
}
