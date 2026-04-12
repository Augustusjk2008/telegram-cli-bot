"""Whisper 语音识别服务"""

import asyncio
import logging
import os
import time
from typing import Optional, Tuple

from bot.config import (
    WHISPER_DEVICE,
    WHISPER_ENABLED,
    WHISPER_LANGUAGE,
    WHISPER_MAX_DURATION,
    WHISPER_MODEL,
    WHISPER_TEMP_DIR,
    WHISPER_TIMEOUT,
)

logger = logging.getLogger(__name__)


class WhisperService:
    """Whisper 语音识别服务（单例模式）"""

    _instance: Optional["WhisperService"] = None
    _model = None
    _model_name: str = ""
    _whisper_available = False
    _pydub_available = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not WHISPER_ENABLED:
            logger.info("Whisper 功能已禁用（WHISPER_ENABLED=false）")
            return

        # 检查依赖
        self._check_dependencies()

        # 延迟加载模型（首次调用时加载）
        if self._whisper_available and (self._model is None or self._model_name != WHISPER_MODEL):
            try:
                self._load_model()
            except Exception as e:
                logger.error(f"Whisper 模型加载失败: {e}")
                self._whisper_available = False

    def _check_dependencies(self):
        """检查依赖库是否可用"""
        try:
            import whisper
            self._whisper_available = True
        except ImportError:
            logger.warning("openai-whisper 未安装，语音识别功能不可用")
            self._whisper_available = False

        try:
            from pydub import AudioSegment
            self._pydub_available = True
        except ImportError:
            logger.warning("pydub 未安装，音频格式转换功能不可用")
            self._pydub_available = False

    def _load_model(self):
        """加载 Whisper 模型"""
        try:
            import whisper
            logger.info(f"正在加载 Whisper 模型: {WHISPER_MODEL} (device={WHISPER_DEVICE})")
            start_time = time.time()
            self._model = whisper.load_model(WHISPER_MODEL, device=WHISPER_DEVICE)
            self._model_name = WHISPER_MODEL
            elapsed = time.time() - start_time
            logger.info(f"Whisper 模型加载完成，耗时 {elapsed:.2f} 秒")
        except Exception as e:
            logger.error(f"加载 Whisper 模型失败: {e}")
            self._model = None
            raise

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return WHISPER_ENABLED and self._whisper_available and self._pydub_available and self._model is not None

    async def convert_oga_to_wav(self, oga_path: str, wav_path: str) -> bool:
        """将 .oga 格式转换为 .wav（异步执行）"""
        if not self._pydub_available:
            logger.error("pydub 不可用，无法转换音频格式")
            return False

        loop = asyncio.get_running_loop()

        def _convert():
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(oga_path, format="ogg")
                audio.export(wav_path, format="wav")
                return True
            except Exception as e:
                logger.error(f"音频格式转换失败: {e}")
                return False

        return await loop.run_in_executor(None, _convert)

    async def transcribe(self, audio_path: str) -> Tuple[bool, str]:
        """
        转录音频文件为文字

        Returns:
            Tuple[bool, str]: (是否成功, 识别结果或错误信息)
        """
        if not self.is_available():
            return False, "Whisper 服务不可用"

        if not os.path.exists(audio_path):
            return False, f"音频文件不存在: {audio_path}"

        loop = asyncio.get_running_loop()

        def _transcribe():
            try:
                from pydub import AudioSegment

                # 检查音频时长
                audio = AudioSegment.from_file(audio_path)
                duration = len(audio) / 1000.0  # 转换为秒
                if duration > WHISPER_MAX_DURATION:
                    return False, f"音频时长超过限制（{WHISPER_MAX_DURATION}秒）"

                # 执行识别
                logger.info(f"开始识别音频: {audio_path} (时长: {duration:.1f}秒)")
                start_time = time.time()

                result = self._model.transcribe(
                    audio_path,
                    language=WHISPER_LANGUAGE if WHISPER_LANGUAGE != "auto" else None,
                    fp16=(WHISPER_DEVICE == "cuda"),  # GPU 使用 fp16 加速
                    verbose=False,
                )

                elapsed = time.time() - start_time
                text = result["text"].strip()
                logger.info(f"识别完成，耗时 {elapsed:.2f} 秒，文本长度: {len(text)}")

                if not text:
                    return False, "未识别到有效内容"

                return True, text

            except Exception as e:
                logger.error(f"Whisper 识别失败: {e}")
                return False, f"识别失败: {str(e)}"

        try:
            # 使用超时保护
            return await asyncio.wait_for(
                loop.run_in_executor(None, _transcribe),
                timeout=WHISPER_TIMEOUT
            )
        except asyncio.TimeoutError:
            return False, f"识别超时（{WHISPER_TIMEOUT}秒）"

    def cleanup_temp_files(self, *file_paths: str):
        """清理临时文件"""
        for path in file_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    logger.debug(f"已删除临时文件: {path}")
            except Exception as e:
                logger.warning(f"删除临时文件失败 {path}: {e}")


# 全局单例
_whisper_service: Optional[WhisperService] = None


def get_whisper_service() -> WhisperService:
    """获取 Whisper 服务实例"""
    global _whisper_service
    if _whisper_service is None:
        _whisper_service = WhisperService()
    return _whisper_service

