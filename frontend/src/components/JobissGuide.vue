<script setup lang="ts">
import mascot from "@/assets/mascot.png";

defineProps<{ message: string }>();
</script>

<template>
  <div class="guide">
    <img class="guide-character" :src="mascot" alt="" aria-hidden="true" />
    <p>{{ message }}</p>
  </div>
</template>
