export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      frictions: {
        Row: {
          created_at: string
          efficacy_class: string | null
          friction_summary: string
          id: number
          mechanism: string
          moment_id: number
          prompt_version: string
          review_notes: string | null
          review_status: Database["public"]["Enums"]["review_status"]
          reviewed_at: string | null
          reviewed_by: string | null
          self_rating: number
        }
        Insert: {
          created_at?: string
          efficacy_class?: string | null
          friction_summary: string
          id?: number
          mechanism: string
          moment_id: number
          prompt_version: string
          review_notes?: string | null
          review_status?: Database["public"]["Enums"]["review_status"]
          reviewed_at?: string | null
          reviewed_by?: string | null
          self_rating: number
        }
        Update: {
          created_at?: string
          efficacy_class?: string | null
          friction_summary?: string
          id?: number
          mechanism?: string
          moment_id?: number
          prompt_version?: string
          review_notes?: string | null
          review_status?: Database["public"]["Enums"]["review_status"]
          reviewed_at?: string | null
          reviewed_by?: string | null
          self_rating?: number
        }
        Relationships: [
          {
            foreignKeyName: "frictions_moment_id_fkey"
            columns: ["moment_id"]
            isOneToOne: false
            referencedRelation: "moments"
            referencedColumns: ["id"]
          },
        ]
      }
      matches: {
        Row: {
          created_at: string
          friction_id: number
          id: number
          match_score: number
          product_id: number | null
          prompt_version: string
          rank: number
          scientific_argument: string
        }
        Insert: {
          created_at?: string
          friction_id: number
          id?: number
          match_score: number
          product_id?: number | null
          prompt_version: string
          rank: number
          scientific_argument: string
        }
        Update: {
          created_at?: string
          friction_id?: number
          id?: number
          match_score?: number
          product_id?: number | null
          prompt_version?: string
          rank?: number
          scientific_argument?: string
        }
        Relationships: [
          {
            foreignKeyName: "matches_friction_id_fkey"
            columns: ["friction_id"]
            isOneToOne: false
            referencedRelation: "frictions"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "matches_product_id_fkey"
            columns: ["product_id"]
            isOneToOne: false
            referencedRelation: "products"
            referencedColumns: ["id"]
          },
        ]
      }
      moments: {
        Row: {
          brand_risk: number | null
          created_at: string
          description: string | null
          id: number
          moment_date: string
          name: string
          prompt_version: string
          purchase_intent: number | null
          score: number | null
          source: Database["public"]["Enums"]["source_kind"]
          source_refs: Json
          trend_velocity: number | null
        }
        Insert: {
          brand_risk?: number | null
          created_at?: string
          description?: string | null
          id?: number
          moment_date: string
          name: string
          prompt_version: string
          purchase_intent?: number | null
          score?: number | null
          source: Database["public"]["Enums"]["source_kind"]
          source_refs?: Json
          trend_velocity?: number | null
        }
        Update: {
          brand_risk?: number | null
          created_at?: string
          description?: string | null
          id?: number
          moment_date?: string
          name?: string
          prompt_version?: string
          purchase_intent?: number | null
          score?: number | null
          source?: Database["public"]["Enums"]["source_kind"]
          source_refs?: Json
          trend_velocity?: number | null
        }
        Relationships: []
      }
      pipeline_runs: {
        Row: {
          code_version: string
          error_message: string | null
          finished_at: string | null
          id: number
          items_processed: number | null
          items_succeeded: number | null
          stage: Database["public"]["Enums"]["pipeline_stage"]
          started_at: string
          status: Database["public"]["Enums"]["pipeline_status"]
        }
        Insert: {
          code_version: string
          error_message?: string | null
          finished_at?: string | null
          id?: number
          items_processed?: number | null
          items_succeeded?: number | null
          stage: Database["public"]["Enums"]["pipeline_stage"]
          started_at?: string
          status: Database["public"]["Enums"]["pipeline_status"]
        }
        Update: {
          code_version?: string
          error_message?: string | null
          finished_at?: string | null
          id?: number
          items_processed?: number | null
          items_succeeded?: number | null
          stage?: Database["public"]["Enums"]["pipeline_stage"]
          started_at?: string
          status?: Database["public"]["Enums"]["pipeline_status"]
        }
        Relationships: []
      }
      playbook_outputs: {
        Row: {
          body: Json
          created_at: string
          friction_id: number
          id: number
          kind: Database["public"]["Enums"]["playbook_kind"]
          prompt_version: string
          review_notes: string | null
          review_status: Database["public"]["Enums"]["review_status"]
          reviewed_at: string | null
          reviewed_by: string | null
        }
        Insert: {
          body: Json
          created_at?: string
          friction_id: number
          id?: number
          kind: Database["public"]["Enums"]["playbook_kind"]
          prompt_version: string
          review_notes?: string | null
          review_status?: Database["public"]["Enums"]["review_status"]
          reviewed_at?: string | null
          reviewed_by?: string | null
        }
        Update: {
          body?: Json
          created_at?: string
          friction_id?: number
          id?: number
          kind?: Database["public"]["Enums"]["playbook_kind"]
          prompt_version?: string
          review_notes?: string | null
          review_status?: Database["public"]["Enums"]["review_status"]
          reviewed_at?: string | null
          reviewed_by?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "playbook_outputs_friction_id_fkey"
            columns: ["friction_id"]
            isOneToOne: false
            referencedRelation: "frictions"
            referencedColumns: ["id"]
          },
        ]
      }
      products: {
        Row: {
          brand: string
          category: string | null
          claims: string[]
          external_id: string
          first_seen_at: string
          id: number
          is_dead_link: boolean
          is_lg: boolean
          key_ingredients: string[]
          last_scraped_at: string
          last_verified_at: string | null
          name: string
          platform: string
          public_url: string
        }
        Insert: {
          brand: string
          category?: string | null
          claims?: string[]
          external_id: string
          first_seen_at?: string
          id?: number
          is_dead_link?: boolean
          is_lg?: boolean
          key_ingredients?: string[]
          last_scraped_at?: string
          last_verified_at?: string | null
          name: string
          platform?: string
          public_url: string
        }
        Update: {
          brand?: string
          category?: string | null
          claims?: string[]
          external_id?: string
          first_seen_at?: string
          id?: number
          is_dead_link?: boolean
          is_lg?: boolean
          key_ingredients?: string[]
          last_scraped_at?: string
          last_verified_at?: string | null
          name?: string
          platform?: string
          public_url?: string
        }
        Relationships: []
      }
      signals_cache: {
        Row: {
          fetched_at: string
          id: number
          payload: Json
          payload_hash: string | null
          source: Database["public"]["Enums"]["source_kind"]
        }
        Insert: {
          fetched_at?: string
          id?: number
          payload: Json
          payload_hash?: string | null
          source: Database["public"]["Enums"]["source_kind"]
        }
        Update: {
          fetched_at?: string
          id?: number
          payload?: Json
          payload_hash?: string | null
          source?: Database["public"]["Enums"]["source_kind"]
        }
        Relationships: []
      }
    }
    Views: {
      review_queue: {
        Row: {
          confidence: number | null
          context_id: number | null
          created_at: string | null
          item_id: number | null
          item_kind: string | null
          preview: string | null
          review_status: Database["public"]["Enums"]["review_status"] | null
        }
        Relationships: []
      }
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      pipeline_stage:
        | "ingest_reddit"
        | "ingest_calendar"
        | "ingest_tiktok"
        | "extract_moments"
        | "score_moments"
        | "analyze_friction"
        | "match_product"
        | "generate_playbook"
        | "apply_confidence_gate"
      pipeline_status: "running" | "success" | "failure" | "partial"
      playbook_kind: "influencer" | "marketing_post" | "product_idea"
      review_status: "pending" | "approved" | "rejected" | "retracted"
      source_kind: "tiktok" | "calendar"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      pipeline_stage: [
        "ingest_reddit",
        "ingest_calendar",
        "ingest_tiktok",
        "extract_moments",
        "score_moments",
        "analyze_friction",
        "match_product",
        "generate_playbook",
        "apply_confidence_gate",
      ],
      pipeline_status: ["running", "success", "failure", "partial"],
      playbook_kind: ["influencer", "marketing_post", "product_idea"],
      review_status: ["pending", "approved", "rejected", "retracted"],
      source_kind: ["tiktok", "calendar"],
    },
  },
} as const
