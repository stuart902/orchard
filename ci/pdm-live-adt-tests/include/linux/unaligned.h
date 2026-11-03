#ifndef PDM_HOST_UNALIGNED_H
#define PDM_HOST_UNALIGNED_H
#include <stdint.h>
static inline uint32_t get_unaligned_le32(const void *p) {const uint8_t *x=p;return (uint32_t)x[0]|(uint32_t)x[1]<<8|(uint32_t)x[2]<<16|(uint32_t)x[3]<<24;}

static inline uint64_t get_unaligned_le64(const void *p) {return get_unaligned_le32(p) | (uint64_t)get_unaligned_le32((const uint8_t *)p+4)<<32;}
static inline void put_unaligned_le32(uint32_t v,void *p) {uint8_t *x=p;for(unsigned i=0;i<4;i++)x[i]=v>>(8*i);}

#endif
