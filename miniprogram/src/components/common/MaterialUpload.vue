<template>
  <view v-if="isOpen" class="modal-mask" @tap="handleClose">
    <view class="modal-body" @tap.stop>
      <view class="flex-between mb-24">
        <text class="title">导入学习资料</text>
        <text class="close-btn" @tap="handleClose">关闭</text>
      </view>
      <view v-if="uploadStatus === 'idle'">
        <view class="grid-actions">
          <button class="action-btn wechat-btn" @tap="handleChooseWechatFile">微信文件</button>
          <button class="action-btn media-btn" @tap="handleChooseMedia">相册与拍照</button>
        </view>
        <view class="preview-box">
          <text v-if="!selectedFile" class="sub empty-tip">未选择文件，请点击上方按钮选取</text>
          <view v-else class="flex-between">
            <text class="file-name">{{ selectedFile.name }}</text>
            <text class="sub">{{ formattedFileSize }}</text>
          </view>
        </view>
        <view v-if="selectedFile" class="mb-24">
          <text class="field-label">资料标题</text>
          <input
            v-model="customTitle"
            class="title-input"
            placeholder="请输入资料标题"
            :maxlength="50"
          />
        </view>
        <button
          class="primary-btn submit-btn"
          :class="{ disabled: !selectedFile }"
          :disabled="!selectedFile"
          @tap="handleStartUpload"
        >
          开始上传
        </button>
      </view>
      <view v-else-if="uploadStatus === 'uploading'" class="flex-center py-40">
        <view class="progress-track">
          <view class="progress-bar" :style="{ width: progress + '%' }" />
        </view>
        <text class="progress-text">{{ progress }}%</text>
        <text class="sub">正在上传资料，请稍候...</text>
      </view>
      <view v-else class="flex-center py-40">
        <view class="ok-badge">OK</view>
        <text class="title">上传成功</text>
        <text class="sub mb-24">资料已提交，后台正在智能解析考点</text>
        <button class="primary-btn" @tap="handleClose">完成</button>
      </view>
    </view>
  </view>
</template>

<script lang="ts">
export { generateIdempotencyKey, validateMaterialFile, type SelectedFileInfo } from '@/utils/file';
</script>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { uploadMaterialFile } from '@/api/material';
import { useMaterialStore } from '@/stores/materialStore';
import type { MaterialItem, MaterialUploadResponse } from '@/types/material';
import { generateIdempotencyKey, validateMaterialFile, type SelectedFileInfo } from '@/utils/file';

interface Props {
  visible?: boolean;
  modelValue?: boolean;
  /** 归属课程文件夹标识；缺省表示未分类上传。 */
  folderId?: string;
}
interface Emits {
  (e: 'update:visible', val: boolean): void;
  (e: 'update:modelValue', val: boolean): void;
  (e: 'close'): void;
  (e: 'success', data: MaterialUploadResponse): void;
}
const props = withDefaults(defineProps<Props>(), {
  visible: false,
  modelValue: false,
  folderId: '',
});
const emit = defineEmits<Emits>();
const store = useMaterialStore();

const isOpen = computed(() => props.visible || props.modelValue);
const uploadStatus = ref<'idle' | 'uploading' | 'success'>('idle');
const progress = ref(0);
const selectedFile = ref<SelectedFileInfo | null>(null);
const customTitle = ref('');

const formattedFileSize = computed(() => {
  const b = selectedFile.value?.size || 0;
  return b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;
});

function handleFilePicked(file: SelectedFileInfo): void {
  const check = validateMaterialFile(file.name, file.size);
  if (!check.valid) {
    uni.showToast({ title: check.error || '文件校验失败', icon: 'none' });
    return;
  }
  selectedFile.value = file;
  customTitle.value = file.name.replace(/\.[^/.]+$/, '');
}

function handleChooseWechatFile(): void {
  if (typeof wx !== 'undefined' && wx.chooseMessageFile) {
    wx.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf', 'docx', 'png', 'jpg', 'jpeg'],
      success: (res: { tempFiles?: Array<{ name: string; path: string; size: number }> }) => {
        const item = res.tempFiles?.[0];
        if (item) {
          handleFilePicked({
            name: item.name,
            path: item.path,
            size: item.size,
            sourceType: 'wechat',
          });
        }
      },
    });
  }
}

function handleChooseMedia(): void {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed', 'original'],
    sourceType: ['album', 'camera'],
    success: (res) => {
      const paths = Array.isArray(res.tempFilePaths) ? res.tempFilePaths : [res.tempFilePaths];
      const path = paths[0];
      if (!path) return;
      const files = res.tempFiles as Array<{ size?: number }> | undefined;
      void resolveMediaSize(path, files?.[0]?.size).then((size) => {
        if (size === null) {
          uni.showToast({ title: '无法获取文件大小，请重新选择', icon: 'none' });
          return;
        }
        const name = path.split('/').pop() || 'photo.jpg';
        handleFilePicked({
          name: name.includes('.') ? name : `${name}.jpg`,
          path,
          size,
          sourceType: 'local',
        });
      });
    },
  });
}

/**
 * Resolve the real byte size of a picked media file.
 *
 * The mini-program runtime does not always populate `tempFiles[0].size`
 * (observed on several real devices). Falling back to a small constant would
 * silently bypass the size gate, so when the size is missing we query
 * `uni.getFileInfo`; if it still cannot be determined we return null and the
 * caller must block the selection.
 */
function resolveMediaSize(path: string, provided?: number): Promise<number | null> {
  if (typeof provided === 'number' && provided > 0) {
    return Promise.resolve(provided);
  }
  return new Promise((resolve) => {
    if (typeof uni === 'undefined' || typeof uni.getFileInfo !== 'function') {
      resolve(null);
      return;
    }
    uni.getFileInfo({
      filePath: path,
      success: (info) => {
        resolve(typeof info.size === 'number' && info.size > 0 ? info.size : null);
      },
      fail: () => resolve(null),
    });
  });
}

async function handleStartUpload(): Promise<void> {
  if (!selectedFile.value) return;
  uploadStatus.value = 'uploading';
  progress.value = 0;
  try {
    const res = await uploadMaterialFile({
      filePath: selectedFile.value.path,
      title: customTitle.value.trim() || selectedFile.value.name,
      sourceType: selectedFile.value.sourceType,
      idempotencyKey: generateIdempotencyKey(),
      folderId: props.folderId || undefined,
      onProgressUpdate: (p) => {
        progress.value = p;
      },
    });
    uploadStatus.value = 'success';
    store.addMaterial(res.data as unknown as MaterialItem);
    emit('success', res.data);
  } catch {
    uploadStatus.value = 'idle';
    uni.showToast({ title: '上传失败，请重试', icon: 'none' });
  }
}

function handleClose(): void {
  emit('update:visible', false);
  emit('update:modelValue', false);
  emit('close');
  uploadStatus.value = 'idle';
  selectedFile.value = null;
  customTitle.value = '';
  progress.value = 0;
}
</script>

<style lang="scss" scoped>
@import './MaterialUpload.scss';
</style>
