CREATE TABLE `connections` (
	`owner_id` text NOT NULL,
	`enrollment_id` text NOT NULL,
	`label` text NOT NULL,
	`port` integer NOT NULL,
	`updated_at` integer NOT NULL,
	PRIMARY KEY(`owner_id`, `enrollment_id`)
);
