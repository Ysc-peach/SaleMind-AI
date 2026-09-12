import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElButton, ElTag, ElTable, ElTableColumn, ElPagination } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/table-column/style/css'
import 'element-plus/es/components/pagination/style/css'
import App from './App.vue'
import { router } from './router'
import './styles/main.css'
import './styles/workflow.css'
import './styles/role-workspaces.css'
import './styles/workflow.css'
const app=createApp(App).use(createPinia()).use(router)
for(const component of [ElButton,ElTag,ElTable,ElTableColumn,ElPagination]) app.use(component)
app.mount('#app')
