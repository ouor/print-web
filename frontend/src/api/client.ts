import axios from 'axios'
import type { AxiosError, AxiosRequestConfig, AxiosResponse } from 'axios'

export const api = axios.create({
  baseURL: '/',
  withCredentials: true,
})

// Orval mutator: lets generated hooks call this single configured instance.
export const apiMutator = <T>(config: AxiosRequestConfig): Promise<T> => {
  return api(config).then((res: AxiosResponse<T>) => res.data)
}

export type ApiError = AxiosError<{ detail?: string }>
