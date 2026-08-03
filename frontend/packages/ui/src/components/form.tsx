"use client";

import * as React from "react";
import {
  useFormContext,
  Controller,
  ControllerProps,
  FieldPath,
  FieldValues,
  FormProvider,
} from "react-hook-form";
import { cn } from "@workspace/ui/lib/utils";
import { Label } from "@workspace/ui/components/label";

const Form = FormProvider;

// Extract render prop params from Controller component
type ControllerRenderProps<
  TFieldValues extends FieldValues,
  TName extends FieldPath<TFieldValues>,
> = Parameters<React.ComponentProps<typeof Controller<TFieldValues, TName>>["render"]>[0];

type FormFieldProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
> = {
  control: ControllerProps<TFieldValues, TName>["control"];
  name: TName;
  render: (props: ControllerRenderProps<TFieldValues, TName>) => React.ReactElement;
};

const FormFieldContext = React.createContext<{ name: string } | null>(null);
const FormItemContext = React.createContext<{ id: string } | null>(null);

function FormField<TFieldValues extends FieldValues, TName extends FieldPath<TFieldValues>>({
  control,
  name,
  render,
}: FormFieldProps<TFieldValues, TName>) {
  const id = React.useId();
  return (
    <FormFieldContext.Provider value={{ name }}>
      <FormItemContext.Provider value={{ id }}>
        <Controller
          control={control}
          name={name}
          render={render}
        />
      </FormItemContext.Provider>
    </FormFieldContext.Provider>
  );
}

function useFormField() {
  const itemContext = React.useContext(FormItemContext);
  const fieldContext = React.useContext(FormFieldContext);
  if (!itemContext || !fieldContext) {
    throw new Error("useFormField must be used within FormField and FormItem");
  }
  return { ...itemContext, ...fieldContext };
}

function FormItem({ className, ...props }: React.ComponentProps<"div">) {
  const id = React.useId();
  return (
    <FormFieldContext.Provider value={{ name: "" }}>
      <FormItemContext.Provider value={{ id }}>
        <div className={cn("space-y-1", className)} {...props} />
      </FormItemContext.Provider>
    </FormFieldContext.Provider>
  );
}

function FormLabel({ className, ...props }: React.ComponentProps<typeof Label>) {
  const { id } = React.useContext(FormItemContext) ?? { id: "" };
  return (
    <Label
      htmlFor={id}
      className={cn("text-sm font-medium leading-tight", className)}
      {...props}
    />
  );
}

function FormControl({ className, ...props }: React.ComponentProps<"div">) {
  const { id } = React.useContext(FormItemContext) ?? { id: "" };
  return (
    <div
      id={id}
      data-slot="form-control"
      className={cn(className)}
      {...props}
    />
  );
}

function FormDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      data-slot="form-description"
      className={cn("text-xs/relaxed text-muted-foreground", className)}
      {...props}
    />
  );
}

function FormMessage({ className, ...props }: React.ComponentProps<"div">) {
  const { name } = useFormField();
  const { formState } = useFormContext();
  const fieldError = (formState.errors as Record<string, unknown>)[name];

  if (!fieldError) return null;

  return (
    <div
      role="alert"
      data-slot="form-message"
      className={cn("text-xs/relaxed text-destructive", className)}
      {...props}
    >
      {typeof fieldError === "object" && fieldError !== null && "message" in fieldError
        ? String((fieldError as { message: unknown }).message)
        : "Invalid value"}
    </div>
  );
}

export {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
};
