<template>
  <view class="course-section">
    <view class="section-head">
      <text class="section-title">我的课程</text>
      <view class="create-btn" role="button" aria-label="新建课程" @tap="createVisible = true">
        <text class="create-plus">+</text>
        <text class="create-text">新建课程</text>
      </view>
    </view>

    <view v-if="folders.length === 0" class="course-empty">
      <text class="empty-text">还没有课程，创建一个开始分类学习</text>
    </view>

    <view v-else class="course-list">
      <CourseCard
        v-for="folder in folders"
        :key="folder.id"
        :folder="folder"
        @enter="handleEnter"
        @rename="handleRename"
        @archive="handleArchive"
      />
    </view>

    <view
      v-if="hasUnclassified"
      class="unclassified-entry"
      role="button"
      aria-label="未分类资料"
      @tap="emit('view-unclassified')"
    >
      <view class="entry-left">
        <text class="entry-title">未分类资料</text>
        <text class="entry-desc">{{ unclassifiedCount }} 份资料待归位</text>
      </view>
      <text class="entry-arrow">&gt;</text>
    </view>

    <view v-if="archivedFolders.length > 0" class="archived-block">
      <text class="archived-heading">已归档课程</text>
      <ArchivedCourseItem
        v-for="folder in archivedFolders"
        :key="folder.id"
        :folder="folder"
        @restore="handleRestore"
      />
    </view>

    <CourseCreateDialog v-model:visible="createVisible" @confirm="handleCreateConfirm" />
    <CourseRenameDialog
      v-model:visible="renameVisible"
      :initial-name="renameTarget ? renameTarget.name : ''"
      @confirm="handleRenameConfirm"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { createFolder, renameFolder, archiveFolder, restoreFolder } from '@/api/folder';
import CourseCard from '@/components/course/CourseCard.vue';
import ArchivedCourseItem from '@/components/course/ArchivedCourseItem.vue';
import CourseCreateDialog from '@/components/course/CourseCreateDialog.vue';
import CourseRenameDialog from '@/components/course/CourseRenameDialog.vue';
import type { FolderItem } from '@/types/folder';

defineOptions({ name: 'CourseListSection' });

interface Props {
  folders?: FolderItem[];
  archivedFolders?: FolderItem[];
  unclassifiedCount?: number;
}

interface Emits {
  (e: 'enter', folder: FolderItem): void;
  (e: 'view-unclassified'): void;
  (e: 'changed'): void;
}

const props = withDefaults(defineProps<Props>(), {
  folders: () => [],
  archivedFolders: () => [],
  unclassifiedCount: 0,
});

const emit = defineEmits<Emits>();

const createVisible = ref(false);
const renameVisible = ref(false);
const renameTarget = ref<FolderItem | null>(null);

const hasUnclassified = computed(() => props.unclassifiedCount > 0);

function handleEnter(folder: FolderItem): void {
  emit('enter', folder);
}

function handleRename(folder: FolderItem): void {
  renameTarget.value = folder;
  renameVisible.value = true;
}

async function handleCreateConfirm(name: string): Promise<void> {
  try {
    await createFolder({ name });
    createVisible.value = false;
    uni.showToast({ title: '课程已创建', icon: 'success' });
    emit('changed');
  } catch {
    uni.showToast({ title: '创建失败，请重试', icon: 'none' });
  }
}

async function handleRenameConfirm(name: string): Promise<void> {
  const target = renameTarget.value;
  if (!target) {
    return;
  }
  try {
    await renameFolder(target.id, { name });
    renameVisible.value = false;
    uni.showToast({ title: '已重命名', icon: 'success' });
    emit('changed');
  } catch {
    uni.showToast({ title: '重命名失败，请重试', icon: 'none' });
  }
}

function handleArchive(folder: FolderItem): void {
  uni.showModal({
    title: '归档课程',
    content: `归档「${folder.name}」后，7 天内可随时恢复`,
    confirmText: '归档',
    confirmColor: '#EF4444',
    cancelText: '取消',
    success: (res) => {
      if (res.confirm) {
        void executeArchive(folder);
      }
    },
  });
}

async function executeArchive(folder: FolderItem): Promise<void> {
  try {
    await archiveFolder(folder.id);
    uni.showToast({ title: '已归档，7 天内可恢复', icon: 'none' });
    emit('changed');
  } catch {
    uni.showToast({ title: '归档失败，请重试', icon: 'none' });
  }
}

async function handleRestore(folder: FolderItem): Promise<void> {
  try {
    await restoreFolder(folder.id);
    uni.showToast({ title: '课程已恢复', icon: 'success' });
    emit('changed');
  } catch {
    uni.showToast({ title: '恢复失败，请重试', icon: 'none' });
  }
}
</script>

<style lang="scss" scoped>
@import './CourseListSection.scss';
</style>
